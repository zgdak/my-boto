#!/usr/bin/env python
# Copyright (c) 2006-2008 Mitch Garnaat http://garnaat.org/
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.
from optparse import OptionParser
from boto.services.servicedef import ServiceDef
from boto.services.submit import Submitter
from boto.services.result import ResultProcessor
import boto
import boto.ec2
import sys, os, StringIO

class BS(object):

    Usage = "usage: %prog [options] config_file command"

    Commands = {'reset' : 'Clear input queue and output bucket',
                'submit' : 'Submit local files to the service',
                'start' : 'Start the service',
                'status' : 'Report on the status of the service buckets and queues',
                'retrieve' : 'Retrieve output generated by a batch',
                'batches' : 'List all batches stored in current output_domain'}
    
    def __init__(self):
        self.service_name = None
        self.parser = OptionParser(usage=self.Usage)
        self.parser.add_option("--help-commands", action="store_true", dest="help_commands",
                               help="provides help on the available commands")
        self.parser.add_option("-a", "--access-key", action="store", type="string",
                               help="your AWS Access Key")
        self.parser.add_option("-s", "--secret-key", action="store", type="string",
                               help="your AWS Secret Access Key")
        self.parser.add_option("-p", "--path", action="store", type="string", dest="path",
                               help="the path to local directory for submit and retrieve")
        self.parser.add_option("-k", "--keypair", action="store", type="string", dest="keypair",
                               help="the SSH keypair used with launched instance(s)")
        self.parser.set_defaults(keypair='pl-aws-hosts')
        self.parser.add_option("-l", "--leave", action="store_true", dest="leave",
                               help="leave the files (don't retrieve) files during retrieve command")
        self.parser.set_defaults(leave=False)
        self.parser.add_option("-n", "--num-instances", action="store", type="string", dest="num_instances",
                               help="the number of launched instance(s)")
        self.parser.set_defaults(num_instances=1)
        self.parser.add_option("-i", "--ignore-dirs", action="append", type="string", dest="ignore",
                               help="directories that should be ignored by submit command")
        self.parser.add_option("-b", "--batch-id", action="store", type="string", dest="batch",
                               help="batch identifier required by the retrieve command")
        self.parser.add_option("-r", "--region", action="store", type="string", 
                               help="amazon region default set to eu-west-1 ")
        self.parser.set_defaults(region='eu-west-1')

    def print_command_help(self):
        print '\nCommands:'
        for key in self.Commands.keys():
            print '  %s\t\t%s' % (key, self.Commands[key])

    def do_reset(self):
        iq = self.sd.get_obj('input_queue')
        if iq:
            print 'clearing out input queue'
            i = 0
            m = iq.read()
            while m:
                i += 1
                iq.delete_message(m)
                m = iq.read()
            print 'deleted %d messages' % i
        ob = self.sd.get_obj('output_bucket')
        ib = self.sd.get_obj('input_bucket')
        if ob:
            if ib and ob.name == ib.name:
                return
            print 'delete generated files in output bucket'
            i = 0
            for k in ob:
                i += 1
                k.delete()
            print 'deleted %d keys' % i

    def do_submit(self):
        if not self.options.path:
            self.parser.error('No path provided')
        if not os.path.exists(self.options.path):
            self.parser.error('Invalid path (%s)' % self.options.path)
        s = Submitter(self.sd)
        t = s.submit_path(self.options.path, None, self.options.ignore, None,
                          None, True, self.options.path)
        print 'A total of %d files were submitted' % t[1]
        print 'Batch Identifier: %s' % t[0]

    def do_start(self):
        ami_id = self.sd.get('ami_id')
        instance_type = self.sd.get('instance_type', 'm1.small')
        security_group = self.sd.get('security_group', 'auto_service')
        if not ami_id:
            self.parser.error('ami_id option is required when starting the service')
        #ec2 = boto.connect_ec2()
        ec2 = boto.ec2.connect_to_region(self.sd.region)
        if not self.sd.has_section('Credentials'):
            self.sd.add_section('Credentials')
            self.sd.set('Credentials', 'aws_access_key_id', ec2.aws_access_key_id)
            self.sd.set('Credentials', 'aws_secret_access_key', ec2.aws_secret_access_key)
        s = StringIO.StringIO()
        self.sd.write(s)
        rs = ec2.get_all_images([ami_id])
        img = rs[0]
        r = img.run(user_data=s.getvalue(), key_name=self.options.keypair,
                    max_count=self.options.num_instances,
                    instance_type=instance_type,
                    security_groups=[security_group])
        print 'Starting AMI: %s' % ami_id
        print 'Reservation %s contains the following instances:' % r.id
        for i in r.instances:
            print '\t%s' % i.id

    def do_status(self):
        iq = self.sd.get_obj('input_queue')
        if iq:
            print 'The input_queue (%s) contains approximately %s messages' % (iq.id, iq.count())
        ob = self.sd.get_obj('output_bucket')
        ib = self.sd.get_obj('input_bucket')
        if ob:
            if ib and ob.name == ib.name:
                return
            total = 0
            for k in ob:
                total += 1
            print 'The output_bucket (%s) contains %d keys' % (ob.name, total)

    def do_retrieve(self):
        if not self.options.path:
            self.parser.error('No path provided')
        if not os.path.exists(self.options.path):
            self.parser.error('Invalid path (%s)' % self.options.path)
        if not self.options.batch:
            self.parser.error('batch identifier is required for retrieve command')
        s = ResultProcessor(self.options.batch, self.sd)
        s.get_results(self.options.path, get_file=(not self.options.leave))

    def do_batches(self):
        d = self.sd.get_obj('output_domain')
        if d:
            print 'Available Batches:'
            rs = d.query("['type'='Batch']")
            for item in rs:
                print '  %s' % item.name
        else:
            self.parser.error('No output_domain specified for service')
            
    def main(self):
        self.options, self.args = self.parser.parse_args()
        if self.options.help_commands:
            self.print_command_help()
            sys.exit(0)
        if len(self.args) != 2:
            self.parser.error("config_file and command are required")
        self.config_file = self.args[0]
        self.sd = ServiceDef(self.config_file)
        self.command = self.args[1]
        if hasattr(self, 'do_%s' % self.command):
            method = getattr(self, 'do_%s' % self.command)
            method()
        else:
            self.parser.error('command (%s) not recognized' % self.command)

if __name__ == "__main__":
    bs = BS()
    bs.main()
